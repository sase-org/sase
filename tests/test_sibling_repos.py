"""Tests for configured sibling repository resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sibling_repos import (
    OPENED_SIBLINGS_FILENAME,
    SIBLING_REPOS_JSON_ENV,
    opened_sibling_names,
    opened_sibling_workspace_dirs,
    record_opened_sibling,
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
    assert repo.workspace_dir == str((workspace / "sase" / "repos" / "core").resolve())
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
    expected = managed_root / "sase-suite" / "sase_10" / "sase" / "repos" / "core"
    assert repo.workspace_dir == str(expected.resolve(strict=False))
    assert not expected.exists()


def test_legacy_strategy_is_ignored(
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
            "workspace": {"root": "adjacent"},
            "sibling_repos": [
                {
                    "name": "chezmoi",
                    "path": str(chezmoi),
                    "workspace": {"strategy": "none"},
                }
            ],
        },
        materialize=False,
    )

    repo = resolution.repos[0]
    assert repo.primary_dir == str(chezmoi.resolve())
    assert repo.workspace_dir == str(
        (tmp_path / "sase_10" / "sase" / "repos" / "chezmoi").resolve()
    )
    assert resolution.warnings


def test_env_aliases_are_sanitized_and_json_is_canonical(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    first = tmp_path / "first"
    second = tmp_path / "second"
    primary.mkdir()
    first.mkdir()
    second.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)
    (tmp_path / "main_4" / "sase" / "repos" / "sase-core").mkdir(parents=True)
    (tmp_path / "main_4" / "sase" / "repos" / "sase.core").mkdir(parents=True)

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
        (tmp_path / "main_4" / "sase" / "repos" / "sase-core").resolve()
    )
    assert env["SASE_SIBLING_REPO_SASE_CORE_2_DIR"] == str(
        (tmp_path / "main_4" / "sase" / "repos" / "sase.core").resolve()
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


def test_record_opened_sibling_unions_by_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    core = tmp_path / "sase-core_10"
    nvim = tmp_path / "sase-nvim_10"

    record_opened_sibling("core", str(core))
    record_opened_sibling("nvim", str(nvim))
    record_opened_sibling("core", str(core))

    marker = json.loads(
        (tmp_path / OPENED_SIBLINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert marker["schema_version"] == 2
    assert [item["name"] for item in marker["siblings"]] == ["core", "nvim"]
    assert marker["siblings"][0]["reason"] == ""
    assert marker["siblings"][0]["opened_at"] == ""
    assert opened_sibling_names(tmp_path) == {"core", "nvim"}
    assert opened_sibling_workspace_dirs(tmp_path) == {
        "core": str(core.resolve(strict=False)),
        "nvim": str(nvim.resolve(strict=False)),
    }


def test_record_opened_sibling_noops_without_artifacts_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    record_opened_sibling("core", str(tmp_path / "sase-core_10"))

    assert not (tmp_path / OPENED_SIBLINGS_FILENAME).exists()
    assert opened_sibling_names(tmp_path) == set()
    assert opened_sibling_workspace_dirs(tmp_path) == {}


def test_opened_sibling_accessors_handle_missing_and_malformed_files(
    tmp_path: Path,
) -> None:
    assert opened_sibling_names(tmp_path) == set()
    assert opened_sibling_workspace_dirs(None) == {}
    assert opened_sibling_workspace_dirs(tmp_path) == {}

    marker = tmp_path / OPENED_SIBLINGS_FILENAME
    marker.write_text("{", encoding="utf-8")
    assert opened_sibling_names(tmp_path) == set()
    assert opened_sibling_workspace_dirs(tmp_path) == {}

    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [
                    {"name": "core", "workspace_dir": "/tmp/core"},
                    {"name": "fallback", "workspace_dir": 7},
                    {"name": "", "workspace_dir": "/tmp/empty"},
                    {"workspace_dir": "/tmp/missing"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert opened_sibling_names(tmp_path) == {"core", "fallback"}
    assert opened_sibling_workspace_dirs(tmp_path) == {
        "core": "/tmp/core",
        "fallback": "",
    }
