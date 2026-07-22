"""Tests for ``sase repo path`` parsing and resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import (
    RepoCloneRecord,
    RepoInventory,
    RepoKind,
    RepoRecord,
)
from sase.sdd.store import write_sdd_store_record
from sase.workspace_provider.store import WorkspaceStore


def test_repo_path_parser_accepts_repo_and_context_options() -> None:
    args = create_parser().parse_args(
        [
            "repo",
            "path",
            "research",
            "--ensure",
            "--project",
            "demo",
            "--workspace",
            "12",
        ]
    )

    assert args.repo_subcommand == "path"
    assert args.repo == "research"
    assert args.ensure is True
    assert args.project == "demo"
    assert args.workspace == 12

    short_args = create_parser().parse_args(
        ["repo", "path", "plans", "-e", "-p", "demo", "-w", "4"]
    )
    assert short_args.ensure is True
    assert short_args.project == "demo"
    assert short_args.workspace == 4


@pytest.mark.parametrize("requested", ["demo", "source-checkout"])
def test_repo_path_resolves_primary_name_and_project_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    requested: str,
) -> None:
    ctx = _project_context(tmp_path)
    primary = _repo_record(
        name="source-checkout",
        kind="primary",
        project="demo",
        path=Path(ctx.primary_workspace_dir),
    )
    _patch_context_and_inventory(monkeypatch, ctx, RepoInventory((primary,)))

    args = create_parser().parse_args(
        ["repo", "path", requested, "--project", "demo", "--workspace", "0"]
    )
    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.strip() == ctx.primary_workspace_dir


@pytest.mark.parametrize("requested", ["research", "shared-research"])
def test_repo_path_resolves_sidecar_role_and_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    requested: str,
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    sidecar_path = Path(ctx.primary_workspace_dir) / "sase" / "repos" / "research"
    sidecar = _repo_record(
        name="research",
        slug="shared-research",
        kind="sidecar",
        project="demo",
        path=sidecar_path,
    )
    _patch_context_and_inventory(
        monkeypatch,
        ctx,
        RepoInventory((primary, sidecar)),
    )

    args = create_parser().parse_args(["repo", "path", requested, "--workspace", "0"])
    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == str(sidecar_path)


def test_repo_path_ensure_materializes_configured_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    source = tmp_path / "primary-sidecar"
    target = Path(ctx.primary_workspace_dir) / "sase" / "repos" / "reports"
    sidecar = _repo_record(
        name="reports",
        slug="shared-reports",
        kind="sidecar",
        project="demo",
        path=source,
        clone_path=target,
        remote_url="https://example.test/shared-reports.git",
    )
    _patch_context_and_inventory(
        monkeypatch,
        ctx,
        RepoInventory((primary, sidecar)),
    )
    calls: list[dict[str, Any]] = []

    def materialize(**kwargs: Any) -> str:
        calls.append(kwargs)
        return str(target)

    monkeypatch.setattr(
        "sase.linked_repos.materialize_linked_repo_workspace",
        materialize,
    )
    args = create_parser().parse_args(
        ["repo", "path", "reports", "--ensure", "--workspace", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert calls == [
        {
            "primary_dir": str(source),
            "workspace_dir": str(target),
            "workspace_num": 0,
            "expected_remote_url": "https://example.test/shared-reports.git",
        }
    ]
    assert capsys.readouterr().out.strip() == str(target)


@pytest.mark.parametrize("requested", ["agents", "demo--agents"])
def test_repo_path_hidden_agents_uses_stable_path_in_numbered_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    requested: str,
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    stable = tmp_path / "state" / "projects" / "demo" / "repos" / "agents"
    agents = RepoRecord(
        name="agents",
        kind="sidecar",
        project="demo",
        project_key="demo",
        path=str(stable),
        exists=False,
        auto_clone=False,
        description="Hidden agent data.",
        source="test",
        env_name=None,
        slug="demo--agents",
        remote_url="git@example.test:acme/demo--agents.git",
        clones=(
            RepoCloneRecord(0, str(stable), False),
            RepoCloneRecord(12, str(stable), False),
        ),
    )
    _patch_context_and_inventory(
        monkeypatch,
        ctx,
        RepoInventory((primary, agents)),
    )
    calls: list[dict[str, Any]] = []

    def materialize(**kwargs: Any) -> str:
        calls.append(kwargs)
        return str(stable)

    monkeypatch.setattr(
        "sase.linked_repos.materialize_linked_repo_workspace",
        materialize,
    )
    args = create_parser().parse_args(
        ["repo", "path", requested, "--ensure", "--workspace", "12"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert calls == [
        {
            "primary_dir": str(stable),
            "workspace_dir": str(stable),
            "workspace_num": 12,
            "expected_remote_url": "git@example.test:acme/demo--agents.git",
        }
    ]
    assert capsys.readouterr().out.strip() == str(stable)


@pytest.mark.parametrize(
    ("storage", "kind", "expected_relpath"),
    [
        ("in_tree", "plans", "sdd/plans"),
        ("separate_repo", "research", ".sase/sdd/research"),
        ("sidecar_repos", "research", "sase/repos/research"),
    ],
)
def test_repo_path_preserves_legacy_sdd_layout_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    storage: str,
    kind: str,
    expected_relpath: str,
) -> None:
    ctx = _project_context(tmp_path)
    primary_path = Path(ctx.primary_workspace_dir)
    primary = _primary_record(ctx)
    _patch_context_and_inventory(monkeypatch, ctx, RepoInventory((primary,)))
    monkeypatch.setattr(
        "sase.main.repo_handler._sidecar_role_disabled",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "sase.sdd.store.get_primary_workspace_dir",
        lambda workspace_dir, _workspace_num: str(workspace_dir),
    )

    if storage == "in_tree":
        monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: "bare_git")
        monkeypatch.setattr(
            "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
            lambda _provider: "in_tree",
        )
    elif storage == "separate_repo":
        write_sdd_store_record(
            primary_path,
            {
                "schema_version": 2,
                "storage": "separate_repo",
                "repo": "acme/demo--sdd",
                "remote_url": "https://example.test/demo--sdd.git",
            },
        )
    else:
        write_sdd_store_record(
            primary_path,
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "sidecars": {
                    "plans": {
                        "repo": "acme/demo--plans",
                        "remote_url": "git@example.test:acme/demo--plans.git",
                    },
                    "research": {
                        "repo": "acme/demo--research",
                        "remote_url": "git@example.test:acme/demo--research.git",
                    },
                },
            },
        )

    args = create_parser().parse_args(["repo", "path", kind, "--workspace", "0"])
    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == str(primary_path / expected_relpath)


def test_repo_path_ensure_materializes_legacy_sdd_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    _patch_context_and_inventory(monkeypatch, ctx, RepoInventory((primary,)))
    monkeypatch.setattr(
        "sase.main.repo_handler._sidecar_role_disabled",
        lambda *_args, **_kwargs: False,
    )
    calls: list[tuple[str | Path, int, str, bool]] = []

    def ensure(
        workspace_dir: str | Path,
        workspace_num: int,
        kind: str,
        *,
        strict: bool,
    ) -> Path:
        calls.append((workspace_dir, workspace_num, kind, strict))
        return Path(workspace_dir) / "sase" / "repos" / kind

    expected = Path(ctx.primary_workspace_dir) / "sase" / "repos" / "research"
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_kind_dir",
        lambda *_args: expected,
    )
    args = create_parser().parse_args(
        ["repo", "path", "research", "--ensure", "--workspace", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert calls == [(ctx.primary_workspace_dir, 0, "research", True)]
    assert capsys.readouterr().out.strip() == str(expected)


@pytest.mark.parametrize(
    ("kind", "name"),
    [("linked", "core"), ("external", "gh:acme/widget")],
)
def test_repo_path_refuses_linked_and_external_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: RepoKind,
    name: str,
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    repo = _repo_record(
        name=name,
        kind=kind,
        project="demo",
        path=tmp_path / kind / name.replace("/", "_"),
    )
    _patch_context_and_inventory(
        monkeypatch,
        ctx,
        RepoInventory((primary, repo)),
    )
    args = create_parser().parse_args(["repo", "path", name, "--workspace", "0"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert f"sase repo open {name}" in output.err


def test_repo_path_honors_disabled_legacy_sidecar_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    primary = _primary_record(ctx)
    _patch_context_and_inventory(monkeypatch, ctx, RepoInventory((primary,)))
    monkeypatch.setattr(
        "sase.main.repo_handler._sidecar_role_disabled",
        lambda *_args, **_kwargs: True,
    )
    args = create_parser().parse_args(["repo", "path", "plans", "--workspace", "0"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "not a primary or sidecar repository" in output.err


def _project_context(tmp_path: Path) -> ProjectContext:
    primary = (tmp_path / "demo").resolve()
    primary.mkdir()
    return ProjectContext(
        project_name="demo",
        project_file=str(tmp_path / "demo.sase"),
        primary_workspace_dir=str(primary),
        store=WorkspaceStore(str(primary)),
    )


def _primary_record(ctx: ProjectContext) -> RepoRecord:
    return _repo_record(
        name="demo",
        kind="primary",
        project="demo",
        path=Path(ctx.primary_workspace_dir),
    )


def _repo_record(
    *,
    name: str,
    kind: RepoKind,
    project: str,
    path: Path,
    clone_path: Path | None = None,
    slug: str | None = None,
    remote_url: str | None = None,
) -> RepoRecord:
    selected_path = clone_path or path
    return RepoRecord(
        name=name,
        kind=kind,
        project=project,
        project_key=project,
        path=str(path.resolve()),
        exists=path.is_dir(),
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=slug,
        remote_url=remote_url,
        clones=(
            RepoCloneRecord(
                workspace_num=0,
                path=str(selected_path.resolve()),
                exists=selected_path.is_dir(),
            ),
        ),
    )


def _patch_context_and_inventory(
    monkeypatch: pytest.MonkeyPatch,
    ctx: ProjectContext,
    inventory: RepoInventory,
) -> None:
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: inventory,
    )
