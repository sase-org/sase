"""Configured repository checkout tests for ``sase repo open``."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sase.linked_repos import opened_linked_repo_records
from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from tests.main.repo_handler_helpers import (
    init_git_repo,
    project_context,
    repo_record,
    set_git_origin,
)


ROOT = Path(__file__).resolve().parents[2]


def _evaluate_sase_core_dir(root: Path) -> str:
    env = os.environ.copy()
    for name in (
        "SASE_CORE_DIR",
        "SASE_CORE_WHEEL",
        "SASE_CORE_WHEEL_CACHE_DIR",
        "SASE_ALLOW_STALE_CORE",
        "SASE_LINKED_REPO_SASE_CORE_DIR",
        "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR",
        "SASE_SIBLING_REPO_CORE_DIR",
        "SASE_SIBLING_REPO_CORE_PRIMARY_DIR",
    ):
        env.pop(name, None)
    result = subprocess.run(
        ["just", "--justfile", str(root / "Justfile"), "--evaluate", "sase_core_dir"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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


def test_repo_open_provider_alias_uses_configured_linked_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    just_root = tmp_path / "just-root"
    just_root.mkdir()
    shutil.copyfile(ROOT / "Justfile", just_root / "Justfile")
    workspace_core = just_root / "sase/repos/linked/sase-core"
    workspace_core.mkdir(parents=True)
    linked = replace(
        repo_record(tmp_path, name="sase-core", kind="linked"),
        path=str(workspace_core),
    )
    set_git_origin(Path(linked.path), "git@github.com:sase-org/sase-core.git")
    sentinel = Path(linked.path) / "agent-work.txt"
    sentinel.write_text("sentinel\n", encoding="utf-8")
    opened_projects: list[str] = []
    audit_calls: list[dict[str, object]] = []

    def prepare_checkout(ctx: ProjectContext, *_args: object, **_kwargs: object) -> str:
        opened_projects.append(ctx.project_name)
        return linked.path

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((linked,)),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        prepare_checkout,
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
            "gh:sase-org/sase-core",
            "--project",
            "demo",
            "--reason",
            "inspect core",
            "--workspace",
            "0",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{linked.path}\n"
    assert opened_projects == ["sase-core"]
    evaluated_core = _evaluate_sase_core_dir(just_root)
    just_selected_core = (just_root / evaluated_core).resolve(strict=True)
    assert just_selected_core == Path(linked.path).resolve(strict=True)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "raise SystemExit(0 if Path(sys.argv[1]).read_text() == 'sentinel\\n' else 1)",
            str(just_selected_core / "agent-work.txt"),
        ],
        check=True,
    )
    assert audit_calls == [
        {
            "host_ctx": host_ctx,
            "repo_name": "sase-core",
            "repo_kind": "linked",
            "workspace_num": 0,
            "path": linked.path,
            "reason": "inspect core",
        }
    ]


def test_repo_open_provider_alias_rejects_existing_external_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")
    host_ctx = project_context(tmp_path)
    primary = replace(
        repo_record(tmp_path, name="demo", kind="primary"),
        path=host_ctx.primary_workspace_dir,
        clones=(RepoCloneRecord(0, host_ctx.primary_workspace_dir, True),),
    )
    linked = repo_record(tmp_path, name="sase-core", kind="linked")
    set_git_origin(Path(linked.path), "git@github.com:sase-org/sase-core.git")
    external_path = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "gh"
        / "sase-org"
        / "sase-core"
    )
    init_git_repo(external_path)
    (external_path / "agent-work.txt").write_text("keep me\n", encoding="utf-8")
    external = RepoRecord(
        name="gh:sase-org/sase-core",
        kind="external",
        project="demo",
        project_key="demo",
        path=str(external_path),
        exists=True,
        auto_clone=False,
        description=None,
        source="opened external",
        env_name=None,
        clones=(RepoCloneRecord(0, str(external_path), True),),
    )

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((primary, linked, external)),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda *_args, **_kwargs: pytest.fail("configured checkout was prepared"),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open",
        lambda **_kwargs: pytest.fail("successful open was recorded"),
    )
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "https://github.com/sase-org/sase-core.git",
            "--project",
            "demo",
            "--reason",
            "inspect core",
            "--workspace",
            "0",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    output = capsys.readouterr()
    assert exc_info.value.code == 2
    assert output.out == ""
    assert "matches configured linked repo 'sase-core'" in output.err
    assert str(external_path) in output.err
    assert linked.path in output.err
    assert (external_path / "agent-work.txt").read_text(encoding="utf-8") == "keep me\n"
    assert opened_linked_repo_records(artifacts) == {}


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
