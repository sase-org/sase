"""Tests for configured sibling repository resolution."""

from __future__ import annotations

import json
from pathlib import Path

from sase.sibling_repos import (
    SIBLING_REPOS_JSON_ENV,
    resolve_sibling_repos_for_project,
)


def _project_file(path: Path, primary_workspace_dir: Path) -> Path:
    path.write_text(f"WORKSPACE_DIR: {primary_workspace_dir}\nNAME: main\n")
    return path


def test_resolves_relative_sibling_from_primary_not_numbered_workspace(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core"
    primary.mkdir()
    workspace.mkdir()
    sibling.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=10,
        config={
            "workspace": {"root": "adjacent"},
            "sibling_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.primary_dir == str(sibling.resolve())
    assert repo.workspace_dir == str((tmp_path / "sase-core_10").resolve())
    assert repo.workspace_num == 10


def test_non_materializing_resolution_uses_managed_workspace_root(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core"
    managed_root = tmp_path / "managed"
    primary.mkdir()
    workspace.mkdir()
    sibling.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=10,
        config={
            "workspace": {"root": str(managed_root), "project_key": "sase-suite"},
            "sibling_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    repo = resolution.repos[0]
    expected = managed_root / "sase-suite" / "sase-core_10"
    assert repo.workspace_dir == str(expected.resolve(strict=False))
    assert not expected.exists()


def test_absolute_none_strategy_uses_primary_path_without_suffix(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    chezmoi = tmp_path / "home" / ".local" / "share" / "chezmoi"
    primary.mkdir()
    chezmoi.mkdir(parents=True)
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(tmp_path / "sase_10"),
        workspace_num=10,
        config={
            "sibling_repos": [
                {
                    "name": "chezmoi",
                    "path": str(chezmoi),
                    "workspace": {"strategy": "none"},
                }
            ]
        },
        materialize=False,
    )

    repo = resolution.repos[0]
    assert repo.primary_dir == str(chezmoi.resolve())
    assert repo.workspace_dir == str(chezmoi.resolve())
    assert repo.workspace_strategy == "none"


def test_env_aliases_are_sanitized_and_json_is_canonical(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    first = tmp_path / "first"
    second = tmp_path / "second"
    primary.mkdir()
    first.mkdir()
    second.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "sibling_repos": [
                {"name": "sase-core", "path": "../first"},
                {"name": "sase.core", "path": "../second"},
            ],
        },
        materialize=False,
    )

    env = resolution.to_env()
    assert env["SASE_SIBLING_REPO_SASE_CORE_DIR"] == str(
        (tmp_path / "first_4").resolve()
    )
    assert env["SASE_SIBLING_REPO_SASE_CORE_2_DIR"] == str(
        (tmp_path / "second_4").resolve()
    )
    loaded = json.loads(env[SIBLING_REPOS_JSON_ENV])
    assert [item["env_name"] for item in loaded] == ["SASE_CORE", "SASE_CORE_2"]


def test_missing_primary_paths_are_omitted(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    primary.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=3,
        config={"sibling_repos": [{"name": "missing", "path": "../missing"}]},
        materialize=False,
    )

    assert resolution.repos == ()
    assert "primary path does not exist" in resolution.warnings[0]
    assert resolution.to_env() == {}
