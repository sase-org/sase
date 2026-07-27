"""Tests for bead CLI workspace resolution behavior."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.sdd_policy_helpers import patched_sdd_policy, set_sdd_policy

from sase.bead.cli import _find_beads_location
from sase.bead.cli_common import (
    auto_commit_bead_store,
    get_project,
    get_read_view,
    resolve_beads_location,
)
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.store import write_sdd_store_record
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def test_find_beads_location_separate_repo_prefers_workspace_local_clone(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace_2, primary, workspace_num=2)
    subdir = workspace_2 / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    _set_sdd_config(monkeypatch, storage="separate_repo")

    root, beads_dirname = _find_beads_location()

    assert root == workspace_2 / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_find_beads_location_local_mode_still_uses_primary_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace_2, primary, workspace_num=2)
    monkeypatch.chdir(workspace_2)
    _set_sdd_config(monkeypatch, storage="local")

    root, beads_dirname = _find_beads_location()

    assert root == primary / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_find_beads_location_sidecar_store_uses_plans_clone(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    primary.mkdir()
    workspace_2.mkdir()
    _write_checkout_marker(workspace_2, primary, workspace_num=2)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )
    plans = workspace_2 / "sase" / "repos" / "plans"
    (plans / "beads").mkdir(parents=True)
    monkeypatch.chdir(workspace_2)

    root, beads_dirname = _find_beads_location()

    assert root == plans
    assert beads_dirname == "beads"


def test_find_beads_location_in_tree_prefers_current_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace_2, primary, workspace_num=2)
    subdir = workspace_2 / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    _set_sdd_config(monkeypatch, storage="in_tree")

    root, beads_dirname = _find_beads_location()

    assert root == workspace_2
    assert beads_dirname == "sdd/beads"


def test_find_beads_location_non_vc_walkup_fallback_when_primary_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "project_2"
    (workspace / ".sase" / "sdd" / "beads").mkdir(parents=True)
    monkeypatch.chdir(workspace)

    with patch("sase.bead.workspace.resolve_primary_workspace", return_value=None):
        root, beads_dirname = _find_beads_location()

    assert root == workspace / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_find_beads_location_non_vc_variant_workspace_maps_to_primary(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)

    primary = tmp_path / "workspaces" / "yserve_yp_last_conv" / "google3"
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)

    variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    variant.mkdir(parents=True)
    monkeypatch.chdir(variant)

    with patched_sdd_policy("local"):
        root, beads_dirname = _find_beads_location()

    assert root == primary / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_get_project_opens_warm_store_without_materialization(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    sdd_dir = primary / ".sase" / "sdd"
    primary.mkdir()
    with BeadProject.init(sdd_dir, beads_dirname="beads"):
        pass
    _write_checkout_marker(primary, primary, workspace_num=1)
    _set_sdd_config(monkeypatch, storage="local")
    monkeypatch.chdir(primary)
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")

    def fail_materialize(*_args, **_kwargs):
        raise AssertionError("warm store should not materialize or pull")

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", fail_materialize)

    with get_project() as project:
        assert project.beads_dir == sdd_dir / "beads"


def test_isolated_fixture_resolves_store_below_pytest_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout)

    location = resolve_beads_location()

    assert location is not None
    assert location.beads_dir == checkout / "sdd" / "beads"
    sandbox = Path(os.environ["SASE_PYTEST_SANDBOX_DIR"]).resolve()
    location.beads_dir.resolve().relative_to(sandbox)


def test_workspace_context_rejects_primary_outside_pytest_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sandbox = tmp_path / "sandbox"
    checkout = sandbox / "checkout"
    production = tmp_path / "production"
    checkout.mkdir(parents=True)
    (production / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(checkout, production, workspace_num=2)
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

    assert resolve_beads_location(cwd=checkout, require_existing=True) is None


def test_plain_checkout_sidecar_record_resolves_read_only_bead_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    plans = checkout / "sase" / "repos" / "plans"
    checkout.mkdir()
    with BeadProject.init(plans, beads_dirname="beads") as project:
        issue = project.create("CI-visible epic", IssueType.PLAN)
    _write_sidecar_record(checkout)
    nested = checkout / "src" / "pkg"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.setattr(
        "sase.bead.cli_common._resolve_workspace_context",
        lambda _cwd: None,
    )

    location = resolve_beads_location(require_existing=True)

    assert location is not None
    assert location.root == plans
    assert location.beads_dir == plans / "beads"
    assert location.beads_dirname == "beads"
    assert location.storage == "sidecar_repos"
    assert location.read_only is True
    with get_read_view() as view:
        assert view.show(issue.id).title == "CI-visible epic"
    with pytest.raises(RuntimeError, match="available for reads only"):
        get_project()


def test_plain_checkout_non_sidecar_record_falls_back_to_legacy_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    write_sdd_store_record(
        checkout,
        {
            "schema_version": 1,
            "storage": "separate_repo",
        },
    )
    monkeypatch.setattr(
        "sase.bead.cli_common._resolve_workspace_context",
        lambda _cwd: None,
    )

    assert resolve_beads_location(cwd=checkout, require_existing=True) is None


def test_plain_checkout_sidecar_record_never_auto_commits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    plans = checkout / "sase" / "repos" / "plans"
    (plans / "beads").mkdir(parents=True)
    _write_sidecar_record(checkout)
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        "sase.bead.cli_common._resolve_workspace_context",
        lambda _cwd: None,
    )

    with patch("sase.sdd.files.commit_sdd_store_files") as commit:
        assert auto_commit_bead_store("must not commit") is False

    commit.assert_not_called()


def _set_sdd_config(monkeypatch, *, storage: str) -> None:
    set_sdd_policy(monkeypatch, storage)


def _write_sidecar_record(checkout: Path) -> None:
    write_sdd_store_record(
        checkout,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )


def _write_checkout_marker(
    checkout: Path,
    primary: Path,
    *,
    workspace_num: int,
    project_name: str = "project",
) -> None:
    marker = {
        "project_name": project_name,
        "project_key": project_name,
        "workspace_num": workspace_num,
        "primary_workspace_dir": str(primary),
        "registry_path": str(primary / ".sase" / "registry.json"),
        "schema_version": 1,
    }
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )
