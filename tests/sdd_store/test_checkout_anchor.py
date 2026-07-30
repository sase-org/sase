from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.paths import sase_projects_dir
from sase.sdd.checkout_anchor import resolve_checkout_anchor


def _register_project(project_name: str, primary: Path) -> None:
    project_dir = sase_projects_dir() / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )


def _write_marker(
    checkout: Path,
    *,
    project_name: str,
    project_key: str,
    primary_workspace_dir: Path,
) -> None:
    marker_path = checkout / ".sase" / "checkout.json"
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_key,
                "workspace_num": 18,
                "primary_workspace_dir": str(primary_workspace_dir),
                "registry_path": str(primary_workspace_dir / "registry.json"),
            }
        ),
        encoding="utf-8",
    )


def test_resolve_checkout_anchor_uses_managed_marker_root(
    tmp_path: Path,
) -> None:
    project_name = "zorg"
    primary = tmp_path / "primary" / project_name
    checkout = tmp_path / "state" / "workspaces" / project_name / "sase_18"
    primary.mkdir(parents=True)
    checkout.mkdir(parents=True)
    _register_project(project_name, primary)
    _write_marker(
        checkout,
        project_name=project_name,
        project_key=project_name,
        primary_workspace_dir=primary,
    )

    result = resolve_checkout_anchor(checkout)

    assert result.primary_root == checkout.resolve()
    assert result.project_name == project_name


@pytest.mark.parametrize("sidecar", ("plans", "beads", "research"))
def test_resolve_checkout_anchor_uses_marker_from_sidecar_path(
    tmp_path: Path,
    sidecar: str,
) -> None:
    project_name = "zorg"
    primary = tmp_path / "primary" / project_name
    checkout = tmp_path / "state" / "workspaces" / project_name / "sase_18"
    sidecar_path = checkout / "sase" / "repos" / sidecar / "nested"
    primary.mkdir(parents=True)
    sidecar_path.mkdir(parents=True)
    _register_project(project_name, primary)
    _write_marker(
        checkout,
        project_name=project_name,
        project_key=project_name,
        primary_workspace_dir=primary,
    )

    result = resolve_checkout_anchor(sidecar_path)

    assert result.primary_root == checkout.resolve()
    assert result.project_name == project_name


def test_resolve_checkout_anchor_uses_marker_from_linked_repo_path(
    tmp_path: Path,
) -> None:
    project_name = "zorg"
    primary = tmp_path / "primary" / project_name
    checkout = tmp_path / "state" / "workspaces" / project_name / "sase_18"
    linked_path = checkout / "sase" / "repos" / "linked" / "sase-core" / "src"
    primary.mkdir(parents=True)
    linked_path.mkdir(parents=True)
    _register_project(project_name, primary)
    _write_marker(
        checkout,
        project_name=project_name,
        project_key=project_name,
        primary_workspace_dir=primary,
    )

    result = resolve_checkout_anchor(linked_path)

    assert result.primary_root == checkout.resolve()
    assert result.project_name == project_name


def test_resolve_checkout_anchor_uses_markerless_checkout_root(
    tmp_path: Path,
) -> None:
    project_name = "zorg"
    checkout = tmp_path / "workspaces" / project_name
    checkout.mkdir(parents=True)
    _register_project(project_name, checkout)

    result = resolve_checkout_anchor(checkout)

    assert result.primary_root == checkout.resolve()
    assert result.project_name == project_name


def test_resolve_checkout_anchor_strips_markerless_sidecar_path(
    tmp_path: Path,
) -> None:
    project_name = "zorg"
    checkout = tmp_path / "workspaces" / project_name
    sidecar_path = checkout / "sase" / "repos" / "plans" / "202607"
    sidecar_path.mkdir(parents=True)
    _register_project(project_name, checkout)

    result = resolve_checkout_anchor(sidecar_path)

    assert result.primary_root == checkout.resolve()
    assert result.project_name == project_name


def test_resolve_checkout_anchor_leaves_unrelated_path_unowned(
    tmp_path: Path,
) -> None:
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()

    result = resolve_checkout_anchor(unrelated)

    assert result.primary_root == unrelated.resolve()
    assert result.project_name is None
