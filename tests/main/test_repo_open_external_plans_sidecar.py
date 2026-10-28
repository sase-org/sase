"""Plans-sidecar provisioning for registered-project ``sase repo open``."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.repo_inventory import RepoInventory
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_records import read_sdd_store_record, write_sdd_store_record
from sase.sdd._store_types import SddMaterializationError
from sase.sdd.links import validate_sdd_tree
from sase.workspace_provider import ExternalRepoCloneResult
from tests.main.repo_handler_helpers import (
    init_git_repo,
    project_context,
    project_record,
    repo_record,
)
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def _init_source_repo(source: Path, origin: Path) -> None:
    init_git_repo(source)
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-q", "-u", "origin", "HEAD"], cwd=source, check=True
    )


def _seed_plans_remote(remote: Path, seed: Path) -> None:
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)


def _write_sidecar_record(primary: Path, plans_remote: Path) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/other--plans",
                    "remote_url": str(plans_remote),
                }
            },
        },
    )


def _patch_open(
    monkeypatch: pytest.MonkeyPatch,
    *,
    host_ctx: object,
    registered_project: object | None,
) -> None:
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
        lambda **_kwargs: RepoInventory(
            (
                repo_record(
                    Path(host_ctx.primary_workspace_dir).parent,
                    name="demo",
                    kind="primary",
                ),
            )
        ),
    )
    records = [] if registered_project is None else [registered_project]
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: records,
    )


def _open_repo(name: str) -> None:
    args = create_parser().parse_args(
        ["repo", "open", name, "-p", "demo", "-r", "port fix", "-w", "0"]
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_repo_command(args)
    assert excinfo.value.code == 0


def test_repo_open_registered_project_clones_own_plans_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")
    host_ctx = project_context(tmp_path)
    source = tmp_path / "other-primary"
    _init_source_repo(source, tmp_path / "other-origin.git")
    plans_remote = tmp_path / "other-plans.git"
    _seed_plans_remote(plans_remote, tmp_path / "other-plans-seed")
    source_plans = source / "sase" / "repos" / "plans"
    clone(plans_remote, source_plans)
    _write_sidecar_record(source, plans_remote)
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("other", source),
    )

    _open_repo("other")
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )
    assert capsys.readouterr().out == f"{expected}\n"
    plans = expected / "sase" / "repos" / "plans"
    assert (plans / "README.md").is_file()
    assert git(["remote", "get-url", "origin"], plans).stdout.strip() == str(
        plans_remote
    )
    assert read_sdd_store_record(expected) == read_sdd_store_record(source)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=expected,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
    assert source_plans.is_dir()


def test_repo_open_plans_provision_is_idempotent_and_upgrades_unprovisioned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    host_ctx = project_context(tmp_path)
    source = tmp_path / "other-primary"
    _init_source_repo(source, tmp_path / "other-origin.git")
    plans_remote = tmp_path / "other-plans.git"
    _seed_plans_remote(plans_remote, tmp_path / "other-plans-seed")
    _write_sidecar_record(source, plans_remote)
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("other", source),
    )
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )

    _open_repo("other")
    capsys.readouterr()
    plans = expected / "sase" / "repos" / "plans"
    record_path = expected / ".sase" / "sdd-store.json"
    subprocess.run(["rm", "-rf", str(plans), str(record_path)], check=True)
    assert not plans.exists()
    assert read_sdd_store_record(expected) is None

    _open_repo("other")
    capsys.readouterr()
    assert (plans / "README.md").is_file()
    assert read_sdd_store_record(expected) == read_sdd_store_record(source)

    extra = plans / "keep-me.txt"
    extra.write_text("local work\n", encoding="utf-8")
    calls: list[Path] = []
    original = ensure_sidecar_sdd_clone

    def spy(clone_dir: Path, remote_url: str, **kwargs: object) -> None:
        calls.append(clone_dir)
        original(clone_dir, remote_url, **kwargs)

    monkeypatch.setattr(
        "sase.main._repo_open_external_sdd.ensure_sidecar_sdd_clone", spy
    )
    _open_repo("other")
    capsys.readouterr()
    assert calls == []
    assert extra.read_text(encoding="utf-8") == "local work\n"
    assert read_sdd_store_record(expected) == read_sdd_store_record(source)


def test_repo_open_skips_provision_without_sidecar_plans_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    host_ctx = project_context(tmp_path)
    source = tmp_path / "other-primary"
    _init_source_repo(source, tmp_path / "other-origin.git")
    write_sdd_store_record(
        source,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/sdd",
            "remote_url": "git@github.com:owner/sdd.git",
            "discovery": "found",
        },
    )
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("other", source),
    )
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )

    _open_repo("other")
    capsys.readouterr()
    assert not (expected / "sase" / "repos" / "plans").exists()
    assert read_sdd_store_record(expected) is None

    source_no_record = tmp_path / "bare-primary"
    _init_source_repo(source_no_record, tmp_path / "bare-origin.git")
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("bare", source_no_record),
    )
    _open_repo("bare")
    capsys.readouterr()
    bare = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "bare"
    )
    assert not (bare / "sase" / "repos" / "plans").exists()
    assert read_sdd_store_record(bare) is None


def test_repo_open_provider_ref_does_not_provision_plans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    host_ctx = project_context(tmp_path)
    write_sdd_store_record(
        Path(host_ctx.primary_workspace_dir),
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/demo--plans",
                    "remote_url": str(tmp_path / "demo-plans.git"),
                }
            },
        },
    )

    def clone_provider(scheme: str, ref: str, dest_dir: str) -> ExternalRepoCloneResult:
        init_git_repo(Path(dest_dir))
        return ExternalRepoCloneResult(
            canonical_name="gh:acme/widget",
            dest_dir=dest_dir,
            default_branch="main",
        )

    _patch_open(monkeypatch, host_ctx=host_ctx, registered_project=None)
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gh"}
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.clone_external_repo", clone_provider
    )
    _open_repo("acme/widget")
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
    assert not (expected / "sase" / "repos" / "plans").exists()
    assert read_sdd_store_record(expected) is None


def test_repo_open_plans_provision_failure_warns_and_still_opens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    host_ctx = project_context(tmp_path)
    source = tmp_path / "other-primary"
    _init_source_repo(source, tmp_path / "other-origin.git")
    _write_sidecar_record(source, tmp_path / "missing-plans.git")
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("other", source),
    )

    def fail_clone(*_args: object, **_kwargs: object) -> None:
        raise SddMaterializationError("clone failed: auth")

    monkeypatch.setattr(
        "sase.main._repo_open_external_sdd.ensure_sidecar_sdd_clone", fail_clone
    )
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )
    _open_repo("other")
    output = capsys.readouterr()
    assert output.out == f"{expected}\n"
    assert "plans sidecar" in output.err
    assert "clone failed: auth" in output.err
    assert "sase repo open other" in output.err
    assert read_sdd_store_record(expected) is None
    assert not (expected / "sase" / "repos" / "plans").exists()


def test_repo_open_then_validate_sdd_tree_from_external_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    host_ctx = project_context(tmp_path)
    host = Path(host_ctx.primary_workspace_dir)
    marker_dir = host / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": "demo",
                "project_key": "demo",
                "workspace_num": 10,
                "primary_workspace_dir": str(host),
                "registry_path": str(host / "registry.json"),
            }
        ),
        encoding="utf-8",
    )
    host_plans_remote = tmp_path / "host-plans.git"
    _seed_plans_remote(host_plans_remote, tmp_path / "host-plans-seed")
    broken = tmp_path / "host-plans-seed" / "202610" / "broken.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("# Broken\n", encoding="utf-8")
    git(["add", "-A"], tmp_path / "host-plans-seed")
    git(["commit", "-m", "broken host plan"], tmp_path / "host-plans-seed")
    git(["push", "origin", "main"], tmp_path / "host-plans-seed")
    write_sdd_store_record(
        host,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/demo--plans",
                    "remote_url": str(host_plans_remote),
                }
            },
        },
    )
    clone(host_plans_remote, host / "sase" / "repos" / "plans")

    source = tmp_path / "other-primary"
    _init_source_repo(source, tmp_path / "other-origin.git")
    plans_remote = tmp_path / "other-plans.git"
    _seed_plans_remote(plans_remote, tmp_path / "other-plans-seed")
    _write_sidecar_record(source, plans_remote)
    _patch_open(
        monkeypatch,
        host_ctx=host_ctx,
        registered_project=project_record("other", source),
    )
    expected = host / "sase" / "repos" / "external" / "projects" / "other"
    _open_repo("other")
    capsys.readouterr()

    monkeypatch.chdir(expected)
    validation = validate_sdd_tree(None)
    assert validation.ok
    assert validation.root == (expected / "sase" / "repos" / "plans").resolve()
    subdir = expected / "lib"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    assert validate_sdd_tree(None).ok
