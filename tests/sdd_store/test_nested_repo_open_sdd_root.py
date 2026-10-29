"""Nested repo-open checkouts resolve their own provisioned plans store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sdd._link_files import resolve_sdd_root
from sase.scripts.validate_committed_plans import (
    _resolve_committed_plans_root,
    _sweep_committed_plans,
    main as validate_committed_plans,
)
from sase.sdd.links import validate_sdd_tree
from sase.sdd.store import resolve_sdd_dir, write_sdd_store_record
from tests.main.repo_handler_helpers import init_git_repo
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def _write_marker(
    checkout: Path,
    *,
    project_name: str,
    primary: Path,
    workspace_num: int = 10,
) -> None:
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_name,
                "workspace_num": workspace_num,
                "primary_workspace_dir": str(primary),
                "registry_path": str(primary / "registry.json"),
            }
        ),
        encoding="utf-8",
    )


def _write_sidecar_record(primary: Path, plans_remote: Path, *, repo: str) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": repo,
                    "remote_url": str(plans_remote),
                }
            },
        },
    )


def _seed_plans(remote: Path, seed: Path, body: str) -> None:
    init_bare_repo(remote)
    clone(remote, seed)
    plan = seed / "202610" / "sample.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(body, encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)


_VALID_PLAN = "---\ntier: tale\n---\n# Valid\n"
_BROKEN_PLAN = "# Broken\n"
_VALID_COMMITTED_PLAN = """---
tier: tale
title: A valid plan
goal: Validate the selected committed plans root
size: small
create_time: 2026-10-01 00:00:00
status: wip
---
# A valid plan

This plan has the required archived fields.
"""


def _nested_checkout(host_checkout: Path, kind: str) -> Path:
    repos = host_checkout / "sase" / "repos"
    nested = (
        repos / "external" / "projects" / "other"
        if kind == "external"
        else repos / "linked" / "other"
    )
    init_git_repo(nested)
    return nested


def _plans_root(tmp_path: Path, name: str, body: str) -> Path:
    remote = tmp_path / f"{name}.git"
    _seed_plans(remote, tmp_path / f"{name}-seed", body)
    root = tmp_path / f"{name}-checkout"
    clone(remote, root)
    return root


def _materialize_nested_plans(
    tmp_path: Path,
    nested: Path,
    name: str,
    body: str,
) -> Path:
    remote = tmp_path / f"{name}.git"
    _seed_plans(remote, tmp_path / f"{name}-seed", body)
    _write_sidecar_record(nested, remote, repo=f"owner/{name}--plans")
    root = nested / "sase" / "repos" / "plans"
    clone(remote, root)
    return root


def test_provisioned_nested_checkout_validates_own_plans_not_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    host_primary = tmp_path / "primary"
    host_checkout = tmp_path / "workspace"
    host_primary.mkdir()
    host_checkout.mkdir()
    _write_marker(host_checkout, project_name="host", primary=host_primary)

    host_remote = tmp_path / "host-plans.git"
    nested_remote = tmp_path / "other-plans.git"
    _seed_plans(host_remote, tmp_path / "host-seed", _VALID_PLAN)
    _seed_plans(nested_remote, tmp_path / "other-seed", _BROKEN_PLAN)
    _write_sidecar_record(host_primary, host_remote, repo="owner/host--plans")
    clone(host_remote, host_checkout / "sase" / "repos" / "plans")
    clone(host_remote, host_primary / "sase" / "repos" / "plans")

    nested = host_checkout / "sase" / "repos" / "external" / "projects" / "other"
    init_git_repo(nested)
    _write_sidecar_record(nested, nested_remote, repo="owner/other--plans")
    clone(nested_remote, nested / "sase" / "repos" / "plans")

    monkeypatch.chdir(nested)
    nested_root = resolve_sdd_root(None)
    assert nested_root == (nested / "sase" / "repos" / "plans").resolve()
    validation = validate_sdd_tree(None)
    assert not validation.ok
    assert any(issue.code == "plan-tier" for issue in validation.issues)
    assert all(issue.code != "invalid-root" for issue in validation.issues)

    subdir = nested / "lib"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    assert resolve_sdd_root(None) == (nested / "sase" / "repos" / "plans").resolve()
    subdir_validation = validate_sdd_tree(None)
    assert not subdir_validation.ok
    assert any(issue.code == "plan-tier" for issue in subdir_validation.issues)


def test_unprovisioned_nested_clone_invalid_root_includes_remedy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    host_primary = tmp_path / "primary"
    host_checkout = tmp_path / "workspace"
    host_primary.mkdir()
    host_checkout.mkdir()
    _write_marker(host_checkout, project_name="host", primary=host_primary)
    host_remote = tmp_path / "host-plans.git"
    _seed_plans(host_remote, tmp_path / "host-seed", _VALID_PLAN)
    _write_sidecar_record(host_primary, host_remote, repo="owner/host--plans")
    clone(host_remote, host_checkout / "sase" / "repos" / "plans")

    nested = host_checkout / "sase" / "repos" / "external" / "projects" / "other"
    init_git_repo(nested)
    monkeypatch.chdir(nested)
    validation = validate_sdd_tree(None)
    assert not validation.ok
    issues = [issue for issue in validation.issues if issue.code == "invalid-root"]
    assert len(issues) == 1
    assert str(nested / "sase" / "repos" / "plans") in issues[0].path
    assert "sase repo open" in issues[0].message
    assert "plans sidecar" in issues[0].message


def test_primary_numbered_and_owner_sidecar_resolution_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_10"
    init_git_repo(primary)
    init_git_repo(workspace)
    _write_marker(workspace, project_name="repo", primary=primary)
    remote = tmp_path / "plans.git"
    _seed_plans(remote, tmp_path / "seed", _VALID_PLAN)
    _write_sidecar_record(primary, remote, repo="owner/repo--plans")
    clone(remote, workspace / "sase" / "repos" / "plans")
    clone(remote, primary / "sase" / "repos" / "plans")

    monkeypatch.chdir(primary)
    assert resolve_sdd_root(None) == (primary / "sase" / "repos" / "plans").resolve()
    assert (
        _resolve_committed_plans_root()
        == (primary / "sase" / "repos" / "plans").resolve()
    )
    assert validate_sdd_tree(None).ok

    monkeypatch.chdir(workspace)
    assert resolve_sdd_root(None) == (workspace / "sase" / "repos" / "plans").resolve()
    assert (
        _resolve_committed_plans_root()
        == (workspace / "sase" / "repos" / "plans").resolve()
    )
    assert validate_sdd_tree(None).ok

    sidecar = workspace / "sase" / "repos" / "plans"
    monkeypatch.chdir(sidecar)
    assert resolve_sdd_root(None) == resolve_sdd_dir(Path.cwd(), 1).resolve()
    assert _resolve_committed_plans_root() == resolve_sdd_dir(Path.cwd(), 1).resolve()


def test_committed_plan_validation_rejects_broken_external_plans_despite_host_env(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    host_primary = tmp_path / "primary"
    host_checkout = tmp_path / "workspace"
    host_primary.mkdir()
    host_checkout.mkdir()
    _write_marker(host_checkout, project_name="host", primary=host_primary)
    host_plans = _plans_root(tmp_path, "host", _VALID_COMMITTED_PLAN)

    nested = _nested_checkout(host_checkout, "external")
    nested_plans = _materialize_nested_plans(tmp_path, nested, "external", _BROKEN_PLAN)
    monkeypatch.setenv("SASE_SDD_PLANS_DIR", str(host_plans))
    monkeypatch.chdir(nested)

    assert _resolve_committed_plans_root() == nested_plans.resolve()
    assert validate_committed_plans() == 1
    output = capsys.readouterr().out
    assert "Committed plan validation failed" in output
    assert "[frontmatter-missing]" in output


@pytest.mark.parametrize("kind", ["external", "linked"])
def test_committed_plan_validation_uses_valid_nested_plans_with_broken_host_env(
    tmp_path: Path,
    monkeypatch,
    capsys,
    kind: str,
) -> None:
    host_primary = tmp_path / "primary"
    host_checkout = tmp_path / "workspace"
    host_primary.mkdir()
    host_checkout.mkdir()
    _write_marker(host_checkout, project_name="host", primary=host_primary)
    host_plans = _plans_root(tmp_path, "host", _BROKEN_PLAN)

    nested = _nested_checkout(host_checkout, kind)
    nested_plans = _materialize_nested_plans(
        tmp_path, nested, f"{kind}-nested", _VALID_COMMITTED_PLAN
    )
    subdir = nested / "lib"
    subdir.mkdir()
    monkeypatch.setenv("SASE_SDD_PLANS_DIR", str(host_plans))
    monkeypatch.chdir(subdir)

    selected_root = _resolve_committed_plans_root(cwd=subdir)
    assert selected_root == nested_plans.resolve()
    assert _sweep_committed_plans(selected_root, cwd=subdir).ok
    assert validate_committed_plans() == 0
    assert "Committed plan validation passed: 1 files" in capsys.readouterr().out

    monkeypatch.delenv("SASE_SDD_PLANS_DIR")
    assert _resolve_committed_plans_root(cwd=subdir) == nested_plans.resolve()
    assert _sweep_committed_plans(nested_plans, cwd=subdir).ok


def test_unprovisioned_nested_checkout_fails_closed_through_main(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    host_primary = tmp_path / "primary"
    host_checkout = tmp_path / "workspace"
    host_primary.mkdir()
    host_checkout.mkdir()
    _write_marker(host_checkout, project_name="host", primary=host_primary)
    host_plans = _plans_root(tmp_path, "host", _VALID_COMMITTED_PLAN)

    nested = _nested_checkout(host_checkout, "external")
    stray_plan = nested / "sase" / "repos" / "plans" / "202610" / "stray.md"
    stray_plan.parent.mkdir(parents=True)
    stray_plan.write_text(_VALID_COMMITTED_PLAN, encoding="utf-8")
    monkeypatch.setenv("SASE_SDD_PLANS_DIR", str(host_plans))
    monkeypatch.chdir(nested)

    expected_root = (nested / "sase" / "repos" / "plans").resolve()
    assert _resolve_committed_plans_root() == expected_root
    assert validate_committed_plans() == 1
    output = capsys.readouterr().out
    assert f"{expected_root}: error [invalid-plans-root]" in output
    assert "Rerun `sase repo open`" in output
    assert "provision its plans sidecar" in output


def test_non_nested_committed_plan_resolution_keeps_explicit_env_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "ordinary"
    init_git_repo(checkout)
    configured = _plans_root(tmp_path, "configured", _VALID_COMMITTED_PLAN)
    monkeypatch.setenv("SASE_SDD_PLANS_DIR", str(configured))
    monkeypatch.chdir(checkout)

    assert _resolve_committed_plans_root() == configured.resolve()
